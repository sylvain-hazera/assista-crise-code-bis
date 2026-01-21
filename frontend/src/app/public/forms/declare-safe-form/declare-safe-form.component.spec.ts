import { ComponentFixture, TestBed } from '@angular/core/testing';

import { DeclareSafeFormComponent } from './declare-safe-form.component';

describe('DeclareSafeFormComponent', () => {
  let component: DeclareSafeFormComponent;
  let fixture: ComponentFixture<DeclareSafeFormComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [DeclareSafeFormComponent]
    })
    .compileComponents();

    fixture = TestBed.createComponent(DeclareSafeFormComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
